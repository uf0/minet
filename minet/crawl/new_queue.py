from typing import Counter, Dict, Iterable, Optional

import sqlite3
import pickle
from os import makedirs
from os.path import join, isfile
from shutil import rmtree
from queue import Empty
from threading import Lock, Condition
from contextlib import contextmanager
from datetime import datetime
from quenouille.constants import TIMER_EPSILON

from minet.crawl.types import CrawlJob
from minet.crawl.utils import iterate_over_cursor


def now() -> float:
    return datetime.now().timestamp()


SQL_CREATE = """
PRAGMA journal_mode=wal;

CREATE TABLE "queue" (
    "index" INTEGER PRIMARY KEY,
    "status" INTEGER NOT NULL DEFAULT 0,
    "id" TEXT NOT NULL,
    "url" TEXT NOT NULL,
    "group" TEXT,
    "depth" INTEGER NOT NULL,
    "spider" TEXT,
    "priority" INTEGER NOT NULL,
    "data" BLOB,
    "parent" TEXT
);
CREATE INDEX "idx_queue_priority_index" ON "queue" ("priority", "index");
CREATE INDEX "idx_queue_status" ON "queue" ("status");

CREATE TABLE "throttle" (
    "group" TEXT PRIMARY KEY,
    "timestamp" REAL NOT NULL
) WITHOUT ROWID;
CREATE INDEX "idx_throttle_timestamp" ON "throttle" ("timestamp");

CREATE TABLE "parallelism" (
    "group" TEXT PRIMARY KEY,
    "count" INTEGER NOT NULL
) WITHOUT ROWID;
"""

SQL_INSERT_JOB = """
INSERT INTO "queue" (
    "index",
    "id",
    "url",
    "group",
    "depth",
    "spider",
    "priority",
    "data",
    "parent"
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

SQL_GET_JOB = """
SELECT
    "queue"."index",
    "queue"."id",
    "queue"."url",
    "queue"."group",
    "queue"."depth",
    "queue"."spider",
    "queue"."priority",
    "queue"."data",
    "queue"."parent"
FROM "queue"
LEFT JOIN "throttle" ON "queue"."group" = "throttle"."group"
LEFT JOIN "parallelism" ON "queue"."group" = "parallelism"."group"
WHERE (
   "queue"."status" = 0
   AND ("throttle"."timestamp" IS NULL OR "throttle"."timestamp" <= ?)
   AND ("parallelism"."count" IS NULL OR "parallelism"."count" < ?)
)
ORDER BY "priority" ASC, "index" %s
LIMIT 1;
"""

SQL_INCREMENT_PARALLELISM = """
INSERT OR REPLACE INTO "parallelism" ("group", "count") VALUES (
    ?,
    COALESCE((SELECT ("count" + 1) FROM "parallelism" WHERE "group" = ? LIMIT 1), 1)
)
"""

SQL_UPDATE_THROTTLE = """
INSERT OR REPLACE INTO "throttle" ("group", "timestamp") VALUES (?, ?);
"""


# TODO: callable throttle, callable parallelism
# TODO: should be able to work with optional group parallelism
# TODO: drop the new_queue name, drop old queue, drop persistqueue dep
# TODO: iteration over the queue for dumping purposes
class CrawlerQueue:
    # Params
    persistent: bool
    resuming: bool
    is_lifo: bool
    group_parallelism: int
    throttle: float

    # State
    tasks: Dict[CrawlJob, int]
    put_connection: sqlite3.Connection
    task_connection: sqlite3.Connection
    counter: int
    cleanup_interval: int
    waiter: Condition
    put_lock: Lock
    task_lock: Lock

    def __init__(
        self,
        path: Optional[str] = None,
        db_name: str = "queue.db",
        resume: bool = False,
        lifo: bool = False,
        group_parallelism: int = 1,
        throttle: float = 0,
        cleanup_interval: int = 1000,
    ):
        self.persistent = True
        self.resuming = False

        if path is None:
            self.persistent = False
            # NOTE: I am not sure this is advisable most of the time
            full_path = "file:%i.db?mode=memory&cache=shared" % id(self)
        else:
            full_path = join(path, db_name)

            if not resume:
                rmtree(path, ignore_errors=True)
            elif isfile(full_path):
                self.resuming = True

            makedirs(path, exist_ok=True)

        self.tasks = {}

        self.is_lifo = lifo

        self.group_parallelism = group_parallelism
        self.throttle = throttle

        self.cleanup_interval = cleanup_interval
        self.counter = 0
        self.current_task_done_count = 0

        self.waiter = Condition()
        self.put_lock = Lock()
        self.task_lock = Lock()

        # NOTE: we need two connection if we are to allow concurrent
        # put and task acquisition.
        self.put_connection = sqlite3.connect(full_path, check_same_thread=False)
        self.task_connection = sqlite3.connect(full_path, check_same_thread=False)

        # Setup
        with self.global_transaction() as cursor:
            if not self.resuming:
                cursor.executescript(SQL_CREATE)
            else:
                # We need to restart our counter
                cursor.execute('SELECT max("index") FROM "queue";')
                self.counter = cursor.fetchone()[0]

                # We need to clear status=1
                cursor.execute('UPDATE "queue" SET "status" = 0 WHERE "status" <> 0;')

                # We can safely drop parallelism info as it is bound to runtime
                cursor.execute('DELETE FROM "parallelism";')

                # Cleanup throttle a bit
                cursor.execute('DELETE FROM "throttle" WHERE "timestamp" < ?', (now(),))

                cursor.connection.commit()
                cursor.execute("VACUUM;")

    @contextmanager
    def put_transaction(self):
        try:
            with self.put_lock, self.put_connection:
                cursor = self.put_connection.cursor()
                yield cursor
        finally:
            cursor.close()

    @contextmanager
    def task_transaction(self):
        try:
            with self.task_lock, self.task_connection:
                cursor = self.task_connection.cursor()
                yield cursor
        finally:
            cursor.close()

    @contextmanager
    def global_transaction(self):
        try:
            with self.put_lock, self.task_lock, self.task_connection:
                cursor = self.task_connection.cursor()
                yield cursor
        finally:
            cursor.close()

    def __count(self, cursor: sqlite3.Cursor) -> int:
        cursor.execute('SELECT count(*) FROM "queue" WHERE "status" = 0;')
        return cursor.fetchone()[0]

    def qsize(self) -> int:
        with self.global_transaction() as cursor:
            return self.__count(cursor)

    def __len__(self) -> int:
        return self.qsize()

    def put_many(self, jobs: Iterable[CrawlJob]) -> int:
        with self.put_transaction() as cursor:
            rows = []

            for job in jobs:
                rows.append(
                    (
                        self.counter,
                        job.id,
                        job.url,
                        job.group,
                        job.depth,
                        job.spider,
                        job.priority,
                        pickle.dumps(job.data) if job.data is not None else None,
                        job.parent,
                    )
                )
                self.counter += 1

            cursor.executemany(SQL_INSERT_JOB, rows)
            count = cursor.rowcount

        # NOTE: we notify the waiter because adding jobs to the queue means
        # there might be one we can do right now
        with self.waiter:
            self.waiter.notify()

        return count

    def put(self, job: CrawlJob) -> None:
        self.put_many((job,))

    # NOTE: we will need to cheat a little bit to work with quenouille here.
    # This method will actually block but raise Empty if the queue is drained.
    # We will also need to handle throttling and group parallelism
    # on our own and use buffer_size=0 on quenouille's size to bypass the
    # optimistic buffer that trumps the true ordering of the given queue.
    def get_nowait(self) -> CrawlJob:
        need_to_wait = False
        need_to_wait_for_at_least = None

        while True:

            # Waiting?
            # NOTE: we wait here so we can: 1. avoid recursion and 2. release
            # the transaction lock
            if need_to_wait:
                with self.waiter:
                    self.waiter.wait(need_to_wait_for_at_least)
                need_to_wait = False
                need_to_wait_for_at_least = None

            with self.task_transaction() as cursor:
                cursor.execute(
                    SQL_GET_JOB % ("ASC" if not self.is_lifo else "DESC"),
                    (now(), self.group_parallelism),
                )
                row = cursor.fetchone()

                if row is None:
                    # Queue really is drained
                    if self.__count(cursor) == 0:
                        raise Empty

                    # We may need to wait for a suitable job
                    # NOTE: here we may wait either for one slot to become
                    # open wrt parallelism or enough time wrt throttling
                    need_to_wait = True

                    cursor.execute('SELECT min("timestamp") FROM "throttle" LIMIT 1;')
                    throttle_row = cursor.fetchone()

                    if throttle_row is not None:
                        need_to_wait_for_at_least = (
                            max(0, throttle_row[0] - now()) + TIMER_EPSILON
                        )

                    continue

                index = row[0]

                # NOTE: sqlite does not always support LIMIT on UPDATE
                cursor.execute(
                    'UPDATE "queue" SET "status" = 1 WHERE "index" = ?;',
                    (index,),
                )

                job = CrawlJob(
                    row[2],
                    id=row[1],
                    group=row[3],
                    depth=row[4],
                    spider=row[5],
                    priority=row[6],
                    data=pickle.loads(row[7]) if row[7] is not None else None,
                    parent=row[8],
                )

                # TODO: callable group parallelism
                if job.group is not None:
                    cursor.execute(SQL_INCREMENT_PARALLELISM, (job.group, job.group))

                # NOTE: jobs are hashable by id
                self.tasks[job] = index

                return job

    def worked_groups(self) -> Counter[str]:
        g = Counter()

        with self.global_transaction() as cursor:
            cursor.execute(
                'SELECT "group", "count" FROM "parallelism" WHERE "count" > 0;'
            )

            for row in iterate_over_cursor(cursor):
                g[row[0]] = row[1]

        return g

    def __cleanup(self, cursor: sqlite3.Cursor) -> None:
        self.current_task_done_count = 0
        cursor.execute('DELETE FROM "parallelism" WHERE "count" < 1;')
        cursor.execute('DELETE FROM "throttle" WHERE "timestamp" < ?', (now(),))
        cursor.connection.commit()
        cursor.execute("VACUUM;")

    def cleanup(self) -> None:
        with self.global_transaction() as cursor:
            self.__cleanup(cursor)

    def __clear(self, cursor: sqlite3.Cursor) -> None:
        self.current_task_done_count = 0
        cursor.execute('DELETE FROM "parallelism";')
        cursor.execute('DELETE FROM "throttle";')
        cursor.connection.commit()
        cursor.execute("VACUUM;")

    def clear(self) -> None:
        with self.global_transaction() as cursor:
            self.__clear(cursor)

    def task_done(self, job: CrawlJob) -> None:
        with self.task_transaction() as cursor:
            index = self.tasks.get(job)

            if index is None:
                raise RuntimeError("job is not being worked")

            cursor.execute('DELETE FROM "queue" WHERE "index" = ?;', (index,))
            cursor.execute(
                'UPDATE "parallelism" SET "count" = "count" - 1 WHERE "group" = ?;',
                (job.group,),
            )

            # TODO: validate parallelism = 1?
            if self.throttle != 0:
                cursor.execute(SQL_UPDATE_THROTTLE, (job.group, now() + self.throttle))

            self.current_task_done_count += 0

            if self.current_task_done_count >= self.cleanup_interval:
                self.__cleanup(cursor)

        with self.waiter:
            self.waiter.notify()

    def close(self) -> None:
        self.put_connection.close()
        self.task_connection.close()

    def __del__(self) -> None:
        self.close()
