
# Shipment Result

*This model accepts additional fields of type unknown.*

## Structure

`ShipmentResult`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `buyerOrderId` | `string` | Required | - |
| `paypalTrackerStatus` | [`ShipmentResultPaypalTrackerStatus \| undefined`](../../doc/models/containers/shipment-result-paypal-tracker-status.md) | Optional | This is a container for any-of cases. |
| `status` | [`Status`](../../doc/models/status.md) | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { ShipmentResult, Status } from 'fairpool-merchant-agent-apilib';

const shipmentResult: ShipmentResult = {
  buyerOrderId: '0000072c-0000-0000-0000-000000000000',
  status: Status.Recorded,
  paypalTrackerStatus: 'String7',
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

