
# Merchant Api Bid Request

## Structure

`MerchantApiBidRequest`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `confirmed` | `boolean` | Required | - |
| `notes` | [`MerchantApiBidRequestNotes \| undefined`](../../doc/models/containers/merchant-api-bid-request-notes.md) | Optional | This is a container for any-of cases. |
| `structured` | `unknown` | Required | - |

## Example

```ts
import { MerchantApiBidRequest } from 'fairpool-merchant-agent-apilib';

const merchantApiBidRequest: MerchantApiBidRequest = {
  confirmed: false,
  structured: { 'key1': 'val1', 'key2': 'val2' },
  notes: 'String5',
};
```

