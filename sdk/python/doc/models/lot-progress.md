
# Lot Progress

*This model accepts additional fields of type Any.*

## Structure

`LotProgress`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `captures_completed` | `int` | Required | - |
| `counts` | `Dict[str, int]` | Required | - |
| `fund_deadline_at` | datetime \| None | Optional | This is a container for any-of cases. |
| `holds_placed` | `int` | Required | - |
| `labels` | `List[str]` | Optional | - |
| `lot_id` | `uuid\|str` | Required | - |
| `moq` | `int` | Required | - |
| `refills_offered` | `int` | Required | - |
| `seats` | `int` | Required | - |
| `status` | `str` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import dateutil.parser
import jsonpickle

from fairpoolmerchantagentapi.models.lot_progress import LotProgress

lot_progress = LotProgress(
    captures_completed=6,
    counts={
        'key0': 31,
        'key1': 32,
        'key2': 33
    },
    holds_placed=184,
    lot_id='00001d4e-0000-0000-0000-000000000000',
    moq=254,
    refills_offered=250,
    seats=62,
    status='status8',
    fund_deadline_at=dateutil.parser.parse('2016-03-13T12:52:32.123Z'),
    labels=[
        'labels4',
        'labels5',
        'labels6'
    ],
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

