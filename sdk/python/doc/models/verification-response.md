
# Verification Response

*This model accepts additional fields of type Any.*

## Structure

`VerificationResponse`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `all_match` | `bool` | Required | - |
| `checked_at` | `datetime` | Required | - |
| `expected_captured_total_cents` | `int` | Required | - |
| `items` | [`List[VerificationItem]`](../../doc/models/verification-item.md) | Required | - |
| `lot_id` | `uuid\|str` | Required | - |
| `matched` | `int` | Required | - |
| `paypal_captured_total_cents` | `int` | Required | - |
| `total` | `int` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import dateutil.parser
import jsonpickle

from fairpoolmerchantagentapi.models.verification_item import VerificationItem
from fairpoolmerchantagentapi.models.verification_response import VerificationResponse

verification_response = VerificationResponse(
    all_match=False,
    checked_at=dateutil.parser.parse('2016-03-13T12:52:32.123Z'),
    expected_captured_total_cents=238,
    items=[
        VerificationItem(
            expected_amount_cents=150,
            match=False,
            paypal_amount_cents=64,
            paypal_capture_id='paypal_capture_id0',
            paypal_capture_status='paypal_capture_status0',
            paypal_order_id='paypal_order_id8',
            additional_properties={
                'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
            }
        )
    ],
    lot_id='00001eee-0000-0000-0000-000000000000',
    matched=64,
    paypal_captured_total_cents=72,
    total=176,
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

