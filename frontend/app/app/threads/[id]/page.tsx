import { redirect } from "next/navigation";

export default async function ThreadDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/app/audit/${id}`);
}
