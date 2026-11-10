# API

```python
client_api = client.client
```

## Class Name

`Api`

## Methods

* [List Bids](../../doc/controllers/api.md#list-bids)
* [Get Bid](../../doc/controllers/api.md#get-bid)
* [List Lots](../../doc/controllers/api.md#list-lots)
* [Get Lot](../../doc/controllers/api.md#get-lot)
* [Submit Bid](../../doc/controllers/api.md#submit-bid)
* [Get Lot Fulfillment](../../doc/controllers/api.md#get-lot-fulfillment)
* [Get Lot Progress](../../doc/controllers/api.md#get-lot-progress)
* [Submit Shipments](../../doc/controllers/api.md#submit-shipments)
* [Get Lot Verification](../../doc/controllers/api.md#get-lot-verification)
* [Get Verification Manifest](../../doc/controllers/api.md#get-verification-manifest)


# List Bids

```python
def list_bids(self)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`MerchantBidList`](../../doc/models/merchant-bid-list.md).

## Example Usage

```python
result = client_api.list_bids()

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```


# Get Bid

```python
def get_bid(self,
           bid_id)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `bid_id` | `uuid\|str` | Template, Required | - |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`BidView`](../../doc/models/bid-view.md).

## Example Usage

```python
bid_id = '00002182-0000-0000-0000-000000000000'

result = client_api.get_bid(bid_id)

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationErrorException`](../../doc/models/http-validation-error-exception.md) |


# List Lots

```python
def list_lots(self,
             q=None,
             status=None)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `q` | str \| None | Query, Optional | This is a container for any-of cases. |
| `status` | str \| None | Query, Optional | This is a container for any-of cases. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`List[MerchantLotSummary]`](../../doc/models/merchant-lot-summary.md).

## Example Usage

```python
result = client_api.list_lots()

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationErrorException`](../../doc/models/http-validation-error-exception.md) |


# Get Lot

```python
def get_lot(self,
           lot_id)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lot_id` | `uuid\|str` | Template, Required | - |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`MerchantLotSummary`](../../doc/models/merchant-lot-summary.md).

## Example Usage

```python
lot_id = '00000a08-0000-0000-0000-000000000000'

result = client_api.get_lot(lot_id)

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationErrorException`](../../doc/models/http-validation-error-exception.md) |


# Submit Bid

```python
def submit_bid(self,
              lot_id,
              body,
              idempotency_key=None)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lot_id` | `uuid\|str` | Template, Required | - |
| `body` | [`MerchantApiBidRequest`](../../doc/models/merchant-api-bid-request.md) | Body, Required | - |
| `idempotency_key` | str \| None | Header, Optional | This is a container for any-of cases. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`BidResponse`](../../doc/models/bid-response.md).

## Example Usage

```python
lot_id = '00000a08-0000-0000-0000-000000000000'

body = MerchantApiBidRequest(
    confirmed=False,
    structured=jsonpickle.decode('{"key1":"val1","key2":"val2"}')
)

result = client_api.submit_bid(
    lot_id,
    body
)

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationErrorException`](../../doc/models/http-validation-error-exception.md) |


# Get Lot Fulfillment

```python
def get_lot_fulfillment(self,
                       lot_id)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lot_id` | `uuid\|str` | Template, Required | - |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`List[FulfillmentRow]`](../../doc/models/fulfillment-row.md).

## Example Usage

```python
lot_id = '00000a08-0000-0000-0000-000000000000'

result = client_api.get_lot_fulfillment(lot_id)

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationErrorException`](../../doc/models/http-validation-error-exception.md) |


# Get Lot Progress

```python
def get_lot_progress(self,
                    lot_id)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lot_id` | `uuid\|str` | Template, Required | - |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`LotProgress`](../../doc/models/lot-progress.md).

## Example Usage

```python
lot_id = '00000a08-0000-0000-0000-000000000000'

result = client_api.get_lot_progress(lot_id)

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationErrorException`](../../doc/models/http-validation-error-exception.md) |


# Submit Shipments

```python
def submit_shipments(self,
                    lot_id,
                    body)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lot_id` | `uuid\|str` | Template, Required | - |
| `body` | [`ShipmentsRequest`](../../doc/models/shipments-request.md) | Body, Required | - |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`ShipmentsResponse`](../../doc/models/shipments-response.md).

## Example Usage

```python
lot_id = '00000a08-0000-0000-0000-000000000000'

body = ShipmentsRequest(
    shipments=[
        ShipmentInput(
            buyer_order_id='00001040-0000-0000-0000-000000000000',
            carrier='carrier6',
            tracking_number='tracking_number2'
        )
    ]
)

result = client_api.submit_shipments(
    lot_id,
    body
)

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationErrorException`](../../doc/models/http-validation-error-exception.md) |


# Get Lot Verification

```python
def get_lot_verification(self,
                        lot_id)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lot_id` | `uuid\|str` | Template, Required | - |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`VerificationResponse`](../../doc/models/verification-response.md).

## Example Usage

```python
lot_id = '00000a08-0000-0000-0000-000000000000'

result = client_api.get_lot_verification(lot_id)

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationErrorException`](../../doc/models/http-validation-error-exception.md) |


# Get Verification Manifest

```python
def get_verification_manifest(self,
                             lot_id)
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lot_id` | `uuid\|str` | Template, Required | - |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `body` property of this instance returns the response data which is of type [`VerificationManifest`](../../doc/models/verification-manifest.md).

## Example Usage

```python
lot_id = '00000a08-0000-0000-0000-000000000000'

result = client_api.get_verification_manifest(lot_id)

if result.is_success():
    print(result.body)
elif result.is_error():
    print(result.errors)
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationErrorException`](../../doc/models/http-validation-error-exception.md) |

