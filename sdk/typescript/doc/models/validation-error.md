
# Validation Error

*This model accepts additional fields of type unknown.*

## Structure

`ValidationError`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `ctx` | `unknown \| undefined` | Optional | - |
| `input` | `unknown \| undefined` | Optional | - |
| `loc` | [`ValidationErrorLoc[]`](../../doc/models/containers/validation-error-loc.md) | Required | This is Array of a container for any-of cases. |
| `msg` | `string` | Required | - |
| `type` | `string` | Required | - |
| `additionalProperties` | `Record<string, unknown>` | Optional | - |

## Example

```ts
import { ValidationError } from 'fairpool-merchant-agent-apilib';

const validationError: ValidationError = {
  loc: [
    'String9'
  ],
  msg: 'msg4',
  type: 'type2',
  ctx: { 'key1': 'val1', 'key2': 'val2' },
  input: { 'key1': 'val1', 'key2': 'val2' },
  additionalProperties: {
    'exampleAdditionalProperty': { 'key1': 'val1', 'key2': 'val2' }
  },
};
```

