
# Shipment Input

## Structure

`ShipmentInput`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `buyer_order_id` | `uuid\|str` | Required | - |
| `carrier` | `str` | Required | **Constraints**: *Maximum Length*: `64` |
| `tracking_number` | `str` | Required | **Constraints**: *Maximum Length*: `128` |

## Example

```python
from fairpoolmerchantagentapi.models.shipment_input import ShipmentInput

shipment_input = ShipmentInput(
    buyer_order_id='000014de-0000-0000-0000-000000000000',
    carrier='carrier8',
    tracking_number='tracking_number4'
)
```

