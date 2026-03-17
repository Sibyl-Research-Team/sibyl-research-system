import { ProjectWorkspaceClient } from "./project-workspace-client";

type PageProps = {
  params: Promise<{ name: string }>;
};

export default async function ProjectPage({ params }: PageProps) {
  const { name } = await params;
  return <ProjectWorkspaceClient project={decodeURIComponent(name)} />;
}
