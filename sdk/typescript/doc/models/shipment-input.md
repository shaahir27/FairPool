
# Shipment Input

## Structure

`ShipmentInput`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `buyerOrderId` | `string` | Required | - |
| `carrier` | `string` | Required | **Constraints**: *Maximum Length*: `64` |
| `trackingNumber` | `string` | Required | **Constraints**: *Maximum Length*: `128` |

## Example

```ts
import { ShipmentInput } from 'fairpool-merchant-agent-apilib';

const shipmentInput: ShipmentInput = {
  buyerOrderId: '000002fc-0000-0000-0000-000000000000',
  carrier: 'carrier0',
  trackingNumber: 'tracking_number6',
};
```

