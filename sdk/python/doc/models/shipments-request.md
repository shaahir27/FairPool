
# Shipments Request

## Structure

`ShipmentsRequest`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `shipments` | [`List[ShipmentInput]`](../../doc/models/shipment-input.md) | Required | **Constraints**: *Minimum Items*: `1`, *Maximum Items*: `100` |

## Example

```python
from fairpoolmerchantagentapi.models.shipment_input import ShipmentInput
from fairpoolmerchantagentapi.models.shipments_request import ShipmentsRequest

shipments_request = ShipmentsRequest(
    shipments=[
        ShipmentInput(
            buyer_order_id='00001040-0000-0000-0000-000000000000',
            carrier='carrier6',
            tracking_number='tracking_number2'
        )
    ]
)
```

