
# Verification Manifest

*This model accepts additional fields of type Any.*

## Structure

`VerificationManifest`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `currency` | `str` | Optional | **Default**: `"USD"` |
| `expected_captured_total_cents` | `int` | Required | - |
| `funded` | `bool` | Required | - |
| `how_to_verify` | `str` | Required | - |
| `items` | [`List[ManifestItem]`](../../doc/models/manifest-item.md) | Required | - |
| `lot_id` | `uuid\|str` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import dateutil.parser
import jsonpickle

from fairpoolmerchantagentapi.models.manifest_item import ManifestItem
from fairpoolmerchantagentapi.models.verification_manifest import VerificationManifest

verification_manifest = VerificationManifest(
    expected_captured_total_cents=110,
    funded=False,
    how_to_verify='how_to_verify0',
    items=[
        ManifestItem(
            amount_cents=238,
            captured_at=dateutil.parser.parse('2016-03-13T12:52:32.123Z'),
            paypal_capture_id='paypal_capture_id0',
            paypal_order_id='paypal_order_id8',
            additional_properties={
                'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
            }
        )
    ],
    lot_id='0000016e-0000-0000-0000-000000000000',
    currency='USD',
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

