import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { MotionProvider } from "@/components/motion";

export const metadata = {
  title: "Frontier Evaluation Control",
  description: "Local long-horizon model evaluation dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en" data-theme="dark" data-scroll-behavior="smooth"><body><MotionProvider><AppShell>{children}</AppShell></MotionProvider></body></html>;
}
