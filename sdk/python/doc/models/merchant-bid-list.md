
# Merchant Bid List

*This model accepts additional fields of type Any.*

## Structure

`MerchantBidList`

## Fields

| Name | Type | Tags | Description |
|  --- | --- | --- | --- |
| `items` | [`List[BidView]`](../../doc/models/bid-view.md) | Required | - |
| `additional_properties` | `Dict[str, Any]` | Optional | - |

## Example

```python
import jsonpickle

from fairpoolmerchantagentapi.models.bid_flag_view import BidFlagView
from fairpoolmerchantagentapi.models.bid_view import BidView
from fairpoolmerchantagentapi.models.merchant_bid_list import MerchantBidList

merchant_bid_list = MerchantBidList(
    items=[
        BidView(
            bid_id='00000e34-0000-0000-0000-000000000000',
            current_revision=26,
            lot_id='00001d56-0000-0000-0000-000000000000',
            status='status0',
            flags=[
                BidFlagView(
                    code='code0',
                    evidence='evidence0',
                    field='field6',
                    severity='severity2',
                    additional_properties={
                        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
                    }
                )
            ],
            reject_reason='String7',
            structured=jsonpickle.decode('{"key1":"val1","key2":"val2"}'),
            additional_properties={
                'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
            }
        )
    ],
    additional_properties={
        'exampleAdditionalProperty': jsonpickle.decode('{"key1":"val1","key2":"val2"}')
    }
)
```

