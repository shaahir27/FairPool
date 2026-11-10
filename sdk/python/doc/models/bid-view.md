
# Bid View

*This model accepts additional fields of type Any.*

## Structure

`BidView`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `bid_id` | `uuid\|str` | Required | - |
| `current_revision` | `int` | Required | - |
| `flags` | [`List[BidFlagView]`](../../doc/models/bid-flag-view.md) | Optional | - |
| `lot_id` | `uuid\|str` | Required | - |
| `reject_reason` | str \| None | Optional | This is a container for any-of cases. |
| `status` | `str` | Required | - |
| `structured` | Any \| None | Optional | This is a container for any-of cases. |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.bid_flag_view import BidFlagView
from fairpoolmerchantagentapi.models.bid_view import BidView

bid_view = BidView(
    bid_id='000017f8-0000-0000-0000-000000000000',
    current_revision=14,
    lot_id='00001392-0000-0000-0000-000000000000',
    status='status0',
    flags=[
        BidFlagView(
            code='code0',
            evidence='evidence0',
            field='field6',
            severity='severity2',
            additional_properties={
                'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
            }
        ),
        BidFlagView(
            code='code0',
            evidence='evidence0',
            field='field6',
            severity='severity2',
            additional_properties={
                'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
            }
        )
    ],
    reject_reason='String7',
    structured=jsonpickle.decode('{"key1":"val1","key2":"val2"}'),
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

