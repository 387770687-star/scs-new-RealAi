import { cookies } from "next/headers";
import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { RealAiEvidenceDrawer } from "@/components/realai/evidence-drawer";
import { RealAiOnboardingGate } from "@/components/realai/onboarding-gate";
import { VaultFilePreviewDialog } from "@/components/realai/vault-file-preview-dialog";
import { RealAiVaultWatch } from "@/components/realai/vault-watch";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { RealAiProvider } from "@/core/realai/store";
import { CommandPalette } from "@/components/workspace/command-palette";
import { GatewayOfflineBanner } from "@/components/workspace/gateway-offline-banner";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";

function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

export async function WorkspaceContent({
  children,
  gatewayUnavailable = false,
}: Readonly<{
  children: React.ReactNode;
  gatewayUnavailable?: boolean;
}>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );

  return (
    <QueryClientProvider>
      <RealAiProvider>
        <SidebarProvider className="h-screen" defaultOpen={initialSidebarOpen}>
          <WorkspaceSidebar />
          <SidebarInset className="min-w-0">
            <GatewayOfflineBanner gatewayUnavailable={gatewayUnavailable} />
            {children}
          </SidebarInset>
        </SidebarProvider>
        <RealAiEvidenceDrawer />
        <VaultFilePreviewDialog />
        <RealAiOnboardingGate />
        <RealAiVaultWatch />
        <CommandPalette />
        <Toaster position="top-center" />
      </RealAiProvider>
    </QueryClientProvider>
  );
}
