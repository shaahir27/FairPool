
# Fulfillment Row

*This model accepts additional fields of type Any.*

## Structure

`FulfillmentRow`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `buyer_order_id` | `uuid\|str` | Required | - |
| `city` | `str` | Required | - |
| `country_code` | `str` | Required | - |
| `item_cents` | `int` | Required | - |
| `line_1` | `str` | Required | - |
| `line_2` | str \| None | Optional | This is a container for any-of cases. |
| `name` | `str` | Required | - |
| `paypal_capture_id` | `str` | Required | - |
| `postal_code` | `str` | Required | - |
| `region` | `str` | Required | - |
| `shipping_cents` | `int` | Required | - |
| `tax_cents` | `int` | Required | - |
| `total_cents` | `int` | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.fulfillment_row import FulfillmentRow

fulfillment_row = FulfillmentRow(
    buyer_order_id='00000204-0000-0000-0000-000000000000',
    city='city0',
    country_code='country_code0',
    item_cents=116,
    line_1='line12',
    name='name0',
    paypal_capture_id='paypal_capture_id2',
    postal_code='postal_code2',
    region='region6',
    shipping_cents=68,
    tax_cents=188,
    total_cents=200,
    line_2='String5',
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

