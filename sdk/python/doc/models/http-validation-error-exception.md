
# Http Validation Error Exception

*This model accepts additional fields of type Any.*

## Structure

`HttpValidationErrorException`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `detail` | [`List[ValidationError]`](../../doc/models/validation-error.md) | Optional | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
try:
    # make the API call
except HttpValidationErrorException as e:
    print(e)
except ApiException as e:
    print(e)
```

