# Minet Library Usage

## Summary

*Generic utilities*

* [multithreaded_fetch](#multithreaded_fetch)
* [multithreaded_resolve](#multithreaded_resolve)

*Platform-related commands*

* [CrowdTangleClient](#crowdtangleclient)
  * [#.leaderboard](#leaderboard)
  * [#.lists](#lists)
  * [#.posts](#posts)
  * [#.search](#search)
  * [#.summary](#summary)
* [MediacloudClient](#mediacloudclient)
  * [#.topic_stories](#topic_stories)

## multithreaded_fetch

Function fetching urls in a multithreaded fashion.

```python
from minet import multithreaded_fetch

# Most basic usage
urls = ['https://google.com', 'https://twitter.com']

for result in multithreaded_fetch(urls):
  print(result.url, result.response.status)

# Using a list of dicts

urls = [
  {
    'url': 'https://google.com',
    'label': 'Google'
  },
  {
    'url': 'https://twitter.com',
    'label': 'Twitter'
  }
]

for result in multithreaded_fetch(urls, key=lambda x: x['url']):
  print(result.item['label'], result.response.status)
```

*Arguments*:

* **iterator** *iterable*: An iterator over urls or arbitrary items, if you provide a `key` argument along with it.
* **key** *?callable*: A function extracting the url to fetch from the items yielded by the provided iterator.
* **request_args** *?callable*: A function returning arguments to pass to the internal `request` helper for a call.
* **threads** *?int* [`25`]: Number of threads to use.
* **throttle** *?float|callable* [`0.2`]: Per-domain throttle in seconds. Or a function taking the domain and current item and returning the throttle to apply.
* **guess_extension** *?bool* [`True`]: Whether to attempt to guess the resource's extension.
* **guess_encoding** *?bool* [`True`]: Whether to attempt to guess the resource's encoding.
* **domain_parallelism** *?int* [`1`]: Max number of urls per domain to hit at the same time.
* **buffer_size** *?int* [`25`]: Max number of items per domain to enqueue into memory in hope of finding a new domain that can be processed immediately.
* **insecure** *?bool* [`False`]: Whether to ignore SSL certification errors when performing requests.
* **timeout** *?float|urllib3.Timeout*: Custom timeout for every request.

*Yields*:

A `FetchWorkerResult` having the following attributes:

* **url** *?string*: the fetched url.
* **item** *any*: original item from the iterator.
* **error** *?Exception*: an error.
* **response** *?urllib3.HTTPResponse*: the http response.
* **meta** *?dict*: additional metadata:
  * **mime** *?string*: resource's mimetype.
  * **ext** *?string*: resource's extension.
  * **encoding** *?string*: resource's encoding.


## multithreaded_resolve

Function resolving url redirections in a multithreaded fashion.

```python
from minet import multithreaded_resolve

# Most basic usage
urls = ['https://bit.ly/whatever', 'https://t.co/whatever']

for result in multithreaded_resolve(urls):
  print(result.stack)

# Using a list of dicts

urls = [
  {
    'url': 'https://bit.ly/whatever',
    'label': 'Bit.ly'
  },
  {
    'url': 'https://t.co/whatever',
    'label': 'Twitter'
  }
]

for result in multithreaded_resolve(urls, key=lambda x: x['url']):
  print(result.stack)
```

*Arguments*:

* **iterator** *iterable*: An iterator over urls or arbitrary items, if you provide a `key` argument along with it.
* **key** *?callable*: A function extracting the url to fetch from the items yielded by the provided iterator.
* **resolve_args** *?callable*: A function returning arguments to pass to the internal `resolve` helper for a call.
* **threads** *?int* [`25`]: Number of threads to use.
* **throttle** *?float|callable* [`0.2`]: Per-domain throttle in seconds. Or a function taking the domain and current item and returning the throttle to apply.
* **max_redirects** *?int* [`5`]: Max number of redirections to follow.
* **follow_refresh_header** *?bool* [`False`]: Whether to follow `Refresh` headers or not.
* **follow_meta_refresh** *?bool* [`False`]: Whether to follow meta refresh tags. It's more costly because we need to stream the start of the response's body and cannot rely on headers alone.
* **buffer_size** *?int* [`25`]: Max number of items per domain to enqueue into memory in hope of finding a new domain that can be processed immediately.
* **insecure** *?bool* [`False`]: Whether to ignore SSL certification errors when performing requests.
* **timeout** *?float|urllib3.Timeout*: Custom timeout for every request.

*Yields*:

A `ResolveWorkerResult` having the following attributes:

* **url** *?string*: the fetched url.
* **item** *any*: original item from the iterator.
* **error** *?Exception*: an error.
* **stack** *?list*: the redirection stack.

## CrowdTangleClient

Client that can be used to access [CrowdTangle](https://www.crowdtangle.com/)'s APIs while ensuring you respect rate limits.

For more details about the CrowdTangle API, be sure to check their [documentation](https://github.com/CrowdTangle/API/wiki).

```python
from minet.crowdtangle import CrowdTangleClient

client = CrowdTangleClient(token='MYTOKEN')

# If you want to use a custom rate limit:
client = CrowdTangleClient(token='MYTOKEN', rate_limit=50)
```

*Arguments*

* **token** *str*: CrowdTangle dashboard API token.
* **rate_limit** *?int* [`6`]: number of allowed hits per minute.

### #.leaderboard

Method yielding stats about the accounts tracked by your dashboard.

```python
for account_stats in client.leaderboard():
  print(account_stats)

# For a specific list:
for account_stats in client.leaderboard(list_id=9457):
  print(account_stats)
```

*Arguments*

* **list_id** *?str*: whether to return only accounts from the given list.
* **limit** *?int*: max number of accounts to return.
* **format** *?str* [`csv_dict_row`]: output format. Can be either `raw` to return raw JSON output from the API, `csv_dict_row` to return items as `OrderedDict` or finally `csv_row` to return plain lists.
* **partition_strategy** *?str|int*: query partition strategy to use to mitigate the APIs issues regarding pagination. Can be either `day` or a number of results before rolling the query. `500` seems to be a good compromise.
* **per_call** *?bool* [`False`]: whether to yield once per API call or once per retrieved item.

### #.lists

Method returning your dashboard's lists.

```python
lists = client.lists()
```

*Arguments*

* **format** *?str* [`csv_dict_row`]: output format. Can be either `raw` to return raw JSON output from the API, `csv_dict_row` to return items as `OrderedDict` or finally `csv_row` to return plain lists.

### #.posts

Method yielding posts from groups or pages tracked by your dashboard.

```python
for post in client.posts():
  print(post)
```

*Arguments*

* **language** *?str*: filter posts by language.
* **list_ids** *?iterable*: retrieve only posts from those lists.
* **sort_by** *?str* [`date`]: how to sort retrieved posts. Can be either `date` or `interaction_date` or `overperforming` or `total_interactions` or `underperforming`.
* **end_date** *?str*: end date.
* **start_date** *?str*: start date.
* **limit** *?int*: max number of posts to return.
* **format** *?str* [`csv_dict_row`]: output format. Can be either `raw` to return raw JSON output from the API, `csv_dict_row` to return items as `OrderedDict` or finally `csv_row` to return plain lists.
* **partition_strategy** *?str|int*: query partition strategy to use to mitigate the APIs issues regarding pagination. Can be either `day` or a number of results before rolling the query. `500` seems to be a good compromise.
* **per_call** *?bool* [`False`]: whether to yield once per API call or once per retrieved item.

### #.search

Method searching for posts based on a given query.

```python
for post in client.search('tree'):
  print(post)
```

*Arguments*

* **terms** *str*: search query.
* **and** *?str*: and component of the query.
* **language** *?str*: filter posts by language.
* **not_in_title** *?bool* [`False`]: whether to search account titles or not.
* **platforms** *?iterable<str>*: only return posts from the given platforms.
* **sort_by** *?str* [`date`]: how to sort retrieved posts. Can be either `date` or `interaction_date` or `overperforming` or `total_interactions` or `underperforming`.
* **end_date** *?str*: end date.
* **start_date** *?str*: start date.
* **types** *?iterable<str>*: only return those post types.
* **limit** *?int*: max number of posts to return.
* **format** *?str* [`csv_dict_row`]: output format. Can be either `raw` to return raw JSON output from the API, `csv_dict_row` to return items as `OrderedDict` or finally `csv_row` to return plain lists.
* **partition_strategy** *?str|int*: query partition strategy to use to mitigate the APIs issues regarding pagination. Can be either `day` or a number of results before rolling the query. `500` seems to be a good compromise.
* **per_call** *?bool* [`False`]: whether to yield once per API call or once per retrieved item.


### #.summary

Method that can be used to compile stats about the given link and optionally return the top 100 posts having shared the link.

```python
stats = client.summary('https://www.lemonde.fr', start_date='2019-01-01')

# If you want top posts
stats, posts = client.summary(
  'https://www.lemonde.fr',
  start_date='2019-01-01',
  with_top_posts=True
)
```

*Arguments*

* **link** *str*: url to query.
* **start_date** *str*: start date for the agregation.
* **format** *?str* [`csv_dict_row`]: output format. Can be either `raw` to return raw JSON output from the API, `csv_dict_row` to return items as `OrderedDict` or finally `csv_row` to return plain lists.
* **sort_by** *?str* [`date`]: how to sort posts. Can be `date`, `subscriber_count` or `total_interactions`.
* **with_top_posts** *?bool*: whether to also return top 100 posts.

## MediacloudClient

Client that can be used to access [Mediacloud](https://mediacloud.org/) APIs.

For more information about their API, check out their [documentation](https://github.com/berkmancenter/mediacloud/blob/master/doc/api_2_0_spec/api_2_0_spec.md) (for [topics](https://github.com/berkmancenter/mediacloud/blob/master/doc/api_2_0_spec/topics_api_2_0_spec.md) and for [admin](https://github.com/berkmancenter/mediacloud/blob/master/doc/api_2_0_spec/admin_api_2_0_spec.md)).

```python
from minet.mediacloud import MediacloudClient

client = MediacloudClient(token='MYAPIKEY')
```

### #.topic_stories

Method yielding all of a given topic's stories.

```python
for story in client.topic_stories(4536):
  print(story)
```

*Arguments*

* **topic_id** *str*: id of target topic.
* **from_media_id** *?str*: return only stories linked from a media having this id.
* **media_id** *?str*: return only stories coming from a media having this id.
* **format** *?str* [`csv_dict_row`]: output format. Can be either `raw` to return raw JSON output from the API, `csv_dict_row` to return items as `OrderedDict` or finally `csv_row` to return plain lists.