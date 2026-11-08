import { AuthForm } from "@/components/AuthForm";

export const metadata = { title: "Kirish" };
export default function LoginPage() {
  return <AuthForm mode="login" />;
}
