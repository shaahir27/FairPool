
# Bid Flag View

*This model accepts additional fields of type Any.*

## Structure

`BidFlagView`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `code` | `str` | Required | - |
| `evidence` | `str` | Required | - |
| `field` | `str` | Required | - |
| `severity` | `str` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.bid_flag_view import BidFlagView

bid_flag_view = BidFlagView(
    code='code0',
    evidence='evidence0',
    field='field6',
    severity='severity2',
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

