
# Merchant Api Bid Request

## Structure

`MerchantApiBidRequest`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `confirmed` | `bool` | Required | - |
| `notes` | str \| None | Optional | This is a container for any-of cases. |
| `structured` | `Any` | Required | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.merchant_api_bid_request import MerchantApiBidRequest

merchant_api_bid_request = MerchantApiBidRequest(
    confirmed=False,
    structured=jsonpickle.decode('{"key1":"val1","key2":"val2"}'),
    notes='String1'
)
```

