
# Shipments Response

*This model accepts additional fields of type Any.*

## Structure

`ShipmentsResponse`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `accepted` | `int` | Required | - |
| `rows` | [`List[ShipmentResult]`](../../doc/models/shipment-result.md) | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.shipment_result import ShipmentResult
from fairpoolmerchantagentapi.models.shipments_response import ShipmentsResponse
from fairpoolmerchantagentapi.models.status import Status

shipments_response = ShipmentsResponse(
    accepted=46,
    rows=[
        ShipmentResult(
            buyer_order_id='0000018c-0000-0000-0000-000000000000',
            status=Status.RECORDED,
            paypal_tracker_status='String7',
            additional_properties={
                'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
            }
        )
    ],
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

