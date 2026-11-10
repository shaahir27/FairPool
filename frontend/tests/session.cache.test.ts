import { beforeEach, describe, expect, it } from "vitest";

import { readClient } from "../src/shared/api/reads";
import { resetSessionCache } from "../src/shared/lib/session";

describe("session cache reset", () => {
  beforeEach(() => {
    readClient.clear();
  });

  it("keeps public reads when a logged-out probe answers 401", () => {
    resetSessionCache();
    readClient.setQueryData(["public-audit"], {ok: true});

    resetSessionCache("out");

    expect(readClient.getQueryData(["public-audit"])).toEqual({ok: true});
  });

  it("clears cached data when a signed-in session ends", () => {
    resetSessionCache("in");
    readClient.setQueryData(["private-me"], {ok: true});

    resetSessionCache("out");

    expect(readClient.getQueryData(["private-me"])).toBeUndefined();
  });
});
