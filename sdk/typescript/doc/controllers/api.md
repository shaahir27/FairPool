# API

```ts
const api = new Api(client);
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

```ts
async listBids(
  requestOptions?: RequestOptions
): Promise<ApiResponse<MerchantBidList>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`MerchantBidList`](../../doc/models/merchant-bid-list.md).

## Example Usage

```ts
try {
  const response = await api.listBids();

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
  }
}
```


# Get Bid

```ts
async getBid(
  bidId: string,
  requestOptions?: RequestOptions
): Promise<ApiResponse<BidView>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `bidId` | `string` | Template, Required | - |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`BidView`](../../doc/models/bid-view.md).

## Example Usage

```ts
const bidId = '00002182-0000-0000-0000-000000000000';

try {
  const response = await api.getBid(bidId);

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
    if (error instanceof HttpValidationError) {
      console.log(error.result);
    }
  }
}
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationError`](../../doc/models/http-validation-error.md) |


# List Lots

```ts
async listLots(
  q?: ListLotsQ,
  status?: ListLotsStatus,
  requestOptions?: RequestOptions
): Promise<ApiResponse<MerchantLotSummary[]>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `q` | [`ListLotsQ \| undefined`](../../doc/models/containers/list-lots-q.md) | Query, Optional | This is a container for any-of cases. |
| `status` | [`ListLotsStatus \| undefined`](../../doc/models/containers/list-lots-status.md) | Query, Optional | This is a container for any-of cases. |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`MerchantLotSummary[]`](../../doc/models/merchant-lot-summary.md).

## Example Usage

```ts
try {
  const response = await api.listLots();

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
    if (error instanceof HttpValidationError) {
      console.log(error.result);
    }
  }
}
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationError`](../../doc/models/http-validation-error.md) |


# Get Lot

```ts
async getLot(
  lotId: string,
  requestOptions?: RequestOptions
): Promise<ApiResponse<MerchantLotSummary>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lotId` | `string` | Template, Required | - |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`MerchantLotSummary`](../../doc/models/merchant-lot-summary.md).

## Example Usage

```ts
const lotId = '00000a08-0000-0000-0000-000000000000';

try {
  const response = await api.getLot(lotId);

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
    if (error instanceof HttpValidationError) {
      console.log(error.result);
    }
  }
}
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationError`](../../doc/models/http-validation-error.md) |


# Submit Bid

```ts
async submitBid(
  lotId: string,
  body: MerchantApiBidRequest,
  idempotencyKey?: SubmitBidIdempotencyKey,
  requestOptions?: RequestOptions
): Promise<ApiResponse<BidResponse>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lotId` | `string` | Template, Required | - |
| `body` | [`MerchantApiBidRequest`](../../doc/models/merchant-api-bid-request.md) | Body, Required | - |
| `idempotencyKey` | [`SubmitBidIdempotencyKey \| undefined`](../../doc/models/containers/submit-bid-idempotency-key.md) | Header, Optional | This is a container for any-of cases. |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`BidResponse`](../../doc/models/bid-response.md).

## Example Usage

```ts
const lotId = '00000a08-0000-0000-0000-000000000000';

const body: MerchantApiBidRequest = {
  confirmed: false,
  structured: { 'key1': 'val1', 'key2': 'val2' },
};

try {
  const response = await api.submitBid(
    lotId,
    body
  );

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
    if (error instanceof HttpValidationError) {
      console.log(error.result);
    }
  }
}
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationError`](../../doc/models/http-validation-error.md) |


# Get Lot Fulfillment

```ts
async getLotFulfillment(
  lotId: string,
  requestOptions?: RequestOptions
): Promise<ApiResponse<FulfillmentRow[]>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lotId` | `string` | Template, Required | - |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`FulfillmentRow[]`](../../doc/models/fulfillment-row.md).

## Example Usage

```ts
const lotId = '00000a08-0000-0000-0000-000000000000';

try {
  const response = await api.getLotFulfillment(lotId);

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
    if (error instanceof HttpValidationError) {
      console.log(error.result);
    }
  }
}
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationError`](../../doc/models/http-validation-error.md) |


# Get Lot Progress

```ts
async getLotProgress(
  lotId: string,
  requestOptions?: RequestOptions
): Promise<ApiResponse<LotProgress>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lotId` | `string` | Template, Required | - |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`LotProgress`](../../doc/models/lot-progress.md).

## Example Usage

```ts
const lotId = '00000a08-0000-0000-0000-000000000000';

try {
  const response = await api.getLotProgress(lotId);

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
    if (error instanceof HttpValidationError) {
      console.log(error.result);
    }
  }
}
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationError`](../../doc/models/http-validation-error.md) |


# Submit Shipments

```ts
async submitShipments(
  lotId: string,
  body: ShipmentsRequest,
  requestOptions?: RequestOptions
): Promise<ApiResponse<ShipmentsResponse>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lotId` | `string` | Template, Required | - |
| `body` | [`ShipmentsRequest`](../../doc/models/shipments-request.md) | Body, Required | - |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`ShipmentsResponse`](../../doc/models/shipments-response.md).

## Example Usage

```ts
const lotId = '00000a08-0000-0000-0000-000000000000';

const body: ShipmentsRequest = {
  shipments: [
    {
      buyerOrderId: '00001040-0000-0000-0000-000000000000',
      carrier: 'carrier6',
      trackingNumber: 'tracking_number2',
    }
  ],
};

try {
  const response = await api.submitShipments(
    lotId,
    body
  );

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
    if (error instanceof HttpValidationError) {
      console.log(error.result);
    }
  }
}
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationError`](../../doc/models/http-validation-error.md) |


# Get Lot Verification

```ts
async getLotVerification(
  lotId: string,
  requestOptions?: RequestOptions
): Promise<ApiResponse<VerificationResponse>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lotId` | `string` | Template, Required | - |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`VerificationResponse`](../../doc/models/verification-response.md).

## Example Usage

```ts
const lotId = '00000a08-0000-0000-0000-000000000000';

try {
  const response = await api.getLotVerification(lotId);

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
    if (error instanceof HttpValidationError) {
      console.log(error.result);
    }
  }
}
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationError`](../../doc/models/http-validation-error.md) |


# Get Verification Manifest

```ts
async getVerificationManifest(
  lotId: string,
  requestOptions?: RequestOptions
): Promise<ApiResponse<VerificationManifest>>
```

## Authentication

This endpoint requires [HTTPBearer](../../doc/auth/oauth-2-bearer-token.md)

## Parameters

| Parameter | Type | Tags | Description |
|  --- | --- | --- | --- |
| `lotId` | `string` | Template, Required | - |
| `requestOptions` | `RequestOptions \| undefined` | Optional | Pass additional request options. |

## Response Type

**200**: Successful Response

This method returns an [`ApiResponse`](../../doc/api-response.md) instance. The `result` property of this instance returns the response data which is of type [`VerificationManifest`](../../doc/models/verification-manifest.md).

## Example Usage

```ts
const lotId = '00000a08-0000-0000-0000-000000000000';

try {
  const response = await api.getVerificationManifest(lotId);

  // Extracting fully parsed response body.
  console.log(response.result);

  // Extracting response status code.
  console.log(response.statusCode);
  // Extracting response headers.
  console.log(response.headers);
  // Extracting response body of type `string | Stream`
  console.log(response.body);
} catch (error) {
  if (error instanceof ApiError) {
    // Extracting response error status code.
    console.log(error.statusCode);
    // Extracting response error headers.
    console.log(error.headers);
    // Extracting response error body of type `string | Stream`.
    console.log(error.body);
    if (error instanceof HttpValidationError) {
      console.log(error.result);
    }
  }
}
```

## Errors

| HTTP Status Code | Error Description | Exception Class |
|  --- | --- | --- |
| 422 | Validation Error | [`HttpValidationError`](../../doc/models/http-validation-error.md) |

