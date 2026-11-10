
# Manifest Item

*This model accepts additional fields of type Any.*

## Structure

`ManifestItem`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `amount_cents` | `int` | Required | - |
| `captured_at` | `datetime` | Required | - |
| `paypal_capture_id` | `str` | Required | - |
| `paypal_order_id` | `str` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import dateutil.parser
import jsonpickle

from fairpoolmerchantagentapi.models.manifest_item import ManifestItem

manifest_item = ManifestItem(
    amount_cents=184,
    captured_at=dateutil.parser.parse('2016-03-13T12:52:32.123Z'),
    paypal_capture_id='paypal_capture_id2',
    paypal_order_id='paypal_order_id0',
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

