import type { ReactNode } from "react";

import { AreaLayout } from "./AreaLayout";

type PublicLayoutProps = {
  perspective: string;
  children: ReactNode;
};

export function PublicLayout({ perspective, children }: PublicLayoutProps) {
  return (
    <AreaLayout workspace={perspective} tabs={[]}>
      {children}
    </AreaLayout>
  );
}
