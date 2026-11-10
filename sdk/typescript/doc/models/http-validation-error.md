
# Http Validation Error

*This model accepts additional fields of type unknown.*

## Structure

`HttpValidationError`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `detail` | [`ValidationError[] \| undefined`](../../doc/models/validation-error.md) | Optional | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
try {
  // make the API call
} catch (error) {
  if (error instanceof HttpValidationError) {
    console.log(error.result);
  }
}
```

