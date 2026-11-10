
# Bid Receipt

*This model accepts additional fields of type Any.*

## Structure

`BidReceipt`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `hash` | `str` | Required | - |
| `signature` | `str` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.bid_receipt import BidReceipt

bid_receipt = BidReceipt(
    hash='hash2',
    signature='signature4',
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

