
# Shipments Request

## Structure

`ShipmentsRequest`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `shipments` | [`ShipmentInput[]`](../../doc/models/shipment-input.md) | Required | **Constraints**: *Minimum Items*: `1`, *Maximum Items*: `100` |

## Example

```ts
import { ShipmentsRequest } from 'fairpool-merchant-agent-apilib';

const shipmentsRequest: ShipmentsRequest = {
  shipments: [
    {
      buyerOrderId: '00001040-0000-0000-0000-000000000000',
      carrier: 'carrier6',
      trackingNumber: 'tracking_number2',
    }
  ],
};
```

