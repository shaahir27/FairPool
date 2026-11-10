
# Merchant Lot Summary

*This model accepts additional fields of type unknown.*

## Structure

`MerchantLotSummary`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `bidCloseAt` | `string` | Required | - |
| `condition` | `string` | Required | - |
| `deliverySlaDays` | `number` | Required | - |
| `lotId` | `string` | Required | - |
| `minReturnDays` | `number` | Required | - |
| `minSeats` | `number` | Required | - |
| `poolId` | `string` | Required | - |
| `productKey` | `string` | Required | - |
| `seats` | `number` | Required | - |
| `status` | `string` | Required | - |
| `variant` | [`MerchantLotSummaryVariant \| undefined`](../../doc/models/containers/merchant-lot-summary-variant.md) | Optional | This is a container for any-of cases. |
| `zoneId` | `string` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { MerchantLotSummary } from 'fairpool-merchant-agent-apilib';

const merchantLotSummary: MerchantLotSummary = {
  bidCloseAt: '2016-03-13T12:52:32.123Z',
  condition: 'condition6',
  deliverySlaDays: 108,
  lotId: '00001d22-0000-0000-0000-000000000000',
  minReturnDays: 200,
  minSeats: 142,
  poolId: '000010c4-0000-0000-0000-000000000000',
  productKey: 'product_key4',
  seats: 42,
  status: 'status8',
  zoneId: 'zone_id6',
  variant: 'String5',
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

