
# Shipments Response

*This model accepts additional fields of type unknown.*

## Structure

`ShipmentsResponse`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `accepted` | `number` | Required | - |
| `rows` | [`ShipmentResult[]`](../../doc/models/shipment-result.md) | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { ShipmentsResponse, Status } from 'fairpool-merchant-agent-apilib';

const shipmentsResponse: ShipmentsResponse = {
  accepted: 154,
  rows: [
    {
      buyerOrderId: '0000018c-0000-0000-0000-000000000000',
      status: Status.Recorded,
      paypalTrackerStatus: 'String7',
      additionalProperties: {
        'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
      },
    }
  ],
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

