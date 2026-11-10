
# Merchant Lot Summary

*This model accepts additional fields of type Any.*

## Structure

`MerchantLotSummary`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `bid_close_at` | `datetime` | Required | - |
| `condition` | `str` | Required | - |
| `delivery_sla_days` | `int` | Required | - |
| `lot_id` | `uuid\|str` | Required | - |
| `min_return_days` | `int` | Required | - |
| `min_seats` | `int` | Required | - |
| `pool_id` | `uuid\|str` | Required | - |
| `product_key` | `str` | Required | - |
| `seats` | `int` | Required | - |
| `status` | `str` | Required | - |
| `variant` | str \| None | Optional | This is a container for any-of cases. |
| `zone_id` | `str` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import dateutil.parser
import jsonpickle

from fairpoolmerchantagentapi.models.merchant_lot_summary import MerchantLotSummary

merchant_lot_summary = MerchantLotSummary(
    bid_close_at=dateutil.parser.parse('2016-03-13T12:52:32.123Z'),
    condition='condition8',
    delivery_sla_days=34,
    lot_id='00001d9c-0000-0000-0000-000000000000',
    min_return_days=126,
    min_seats=216,
    pool_id='0000104a-0000-0000-0000-000000000000',
    product_key='product_key6',
    seats=224,
    status='status0',
    zone_id='zone_id4',
    variant='String3',
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

