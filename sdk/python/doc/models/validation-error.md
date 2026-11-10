
# Validation Error

*This model accepts additional fields of type Any.*

## Structure

`ValidationError`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `ctx` | `Any` | Optional | - |
| `input` | `Any` | Optional | - |
| `loc` | List[str \| int] | Required | This is List of a container for any-of cases. |
| `msg` | `str` | Required | - |
| `mtype` | `str` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.validation_error import ValidationError

validation_error = ValidationError(
    loc=[
        'String9',
        'String0',
        'String1'
    ],
    msg='msg4',
    mtype='type2',
    ctx=jsonpickle.decode('{"key1":"val1","key2":"val2"}'),
    input=jsonpickle.decode('{"key1":"val1","key2":"val2"}'),
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

