
# Verification Item

*This model accepts additional fields of type Any.*

## Structure

`VerificationItem`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `expected_amount_cents` | `int` | Required | - |
| `match` | `bool` | Required | - |
| `paypal_amount_cents` | `int` | Required | - |
| `paypal_capture_id` | `str` | Required | - |
| `paypal_capture_status` | `str` | Required | - |
| `paypal_order_id` | `str` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.verification_item import VerificationItem

verification_item = VerificationItem(
    expected_amount_cents=80,
    match=False,
    paypal_amount_cents=38,
    paypal_capture_id='paypal_capture_id2',
    paypal_capture_status='paypal_capture_status2',
    paypal_order_id='paypal_order_id0',
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

