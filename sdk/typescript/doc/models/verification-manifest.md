
# Verification Manifest

*This model accepts additional fields of type unknown.*

## Structure

`VerificationManifest`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `currency` | `string \| undefined` | Optional | **Default**: `'USD'` |
| `expectedCapturedTotalCents` | `number` | Required | - |
| `funded` | `boolean` | Required | - |
| `howToVerify` | `string` | Required | - |
| `items` | [`ManifestItem[]`](../../doc/models/manifest-item.md) | Required | - |
| `lotId` | `string` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { VerificationManifest } from 'fairpool-merchant-agent-apilib';

const verificationManifest: VerificationManifest = {
  expectedCapturedTotalCents: 56,
  funded: false,
  howToVerify: 'how_to_verify6',
  items: [
    {
      amountCents: 238,
      capturedAt: '2016-03-13T12:52:32.123Z',
      paypalCaptureId: 'paypal_capture_id0',
      paypalOrderId: 'paypal_order_id8',
      additionalProperties: {
        'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
      },
    }
  ],
  lotId: '00002094-0000-0000-0000-000000000000',
  currency: 'USD',
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

