"use client";

import dynamic from "next/dynamic";

import { useI18n } from "@/i18n/provider";

function ProjectWorkspaceLoading() {
  const { t } = useI18n();
  return (
    <div className="space-y-4">
      <section className="panel-surface rounded-[34px] px-6 py-10 text-sm text-stone-500 md:px-8">
        {t("preparingWorkspace")}
      </section>
    </div>
  );
}

const ProjectWorkspace = dynamic(
  () => import("./project-workspace").then((module) => module.ProjectWorkspace),
  {
    ssr: false,
    loading: () => <ProjectWorkspaceLoading />,
  },
);

export function ProjectWorkspaceClient({ project }: { project: string }) {
  return <ProjectWorkspace project={project} />;
}
