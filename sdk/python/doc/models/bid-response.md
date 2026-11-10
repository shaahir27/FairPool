
# Bid Response

*This model accepts additional fields of type Any.*

## Structure

`BidResponse`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `bid_id` | `uuid\|str` | Required | - |
| `receipt` | [`BidReceipt`](../../doc/models/bid-receipt.md) | Required | - |
| `revision` | `int` | Required | - |
| `status` | `str` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.bid_receipt import BidReceipt
from fairpoolmerchantagentapi.models.bid_response import BidResponse

bid_response = BidResponse(
    bid_id='000004a8-0000-0000-0000-000000000000',
    receipt=BidReceipt(
        hash='hash0',
        signature='signature2',
        additional_properties={
            'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
        }
    ),
    revision=240,
    status='status6',
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

