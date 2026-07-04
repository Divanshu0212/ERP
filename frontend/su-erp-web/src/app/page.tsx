import { redirect } from "next/navigation";

// The app has no marketing home; send visitors to sign in. Route guards then
// forward authenticated users to their role dashboard.
export default function Home() {
  redirect("/login");
}
