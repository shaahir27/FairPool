import type { ApiComponents } from "../api/client";

export type DeliveryAddress = ApiComponents["schemas"]["DeliveryAddress"];
export const EMPTY_DELIVERY_ADDRESS: DeliveryAddress = { name: "", line1: "", line2: "", city: "", region: "", postal_code: "", country_code: "US" };
