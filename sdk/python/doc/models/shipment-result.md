
# Shipment Result

*This model accepts additional fields of type Any.*

## Structure

`ShipmentResult`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `buyer_order_id` | `uuid\|str` | Required | - |
| `paypal_tracker_status` | str \| None | Optional | This is a container for any-of cases. |
| `status` | [`Status`](../../doc/models/status.md) | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.shipment_result import ShipmentResult
from fairpoolmerchantagentapi.models.status import Status

shipment_result = ShipmentResult(
    buyer_order_id='00002534-0000-0000-0000-000000000000',
    status=Status.RECORDED,
    paypal_tracker_status='String5',
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

