import type { Metadata } from "next";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { addMemberAction, changeMemberRoleAction, removeMemberAction } from "@/lib/actions/companies";
import { can, getCompany, getCurrentUser, getMembers } from "@/lib/dal";
import { interpolate } from "@/lib/i18n/interpolate";
import { getDictionary } from "@/lib/i18n/server";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getDictionary();
  return { title: t.members.title };
}

const COMPANY_ROLES = ["PME_DIRIGEANT", "PME_COMPTABLE", "PME_LECTEUR"] as const;

export default async function MembersPage({
  params,
}: PageProps<"/[lang]/dossiers/[companyId]/parametres/utilisateurs">) {
  const { companyId } = await params;
  const [{ t }, company, members, me] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getMembers(companyId),
    getCurrentUser(),
  ]);
  const manage = can(company, "members:manage");
  const roleOptions = COMPANY_ROLES.map((role) => ({ value: role, label: t.roles[role] }));

  return (
    <>
      <PageHeader title={t.members.title} subtitle={t.members.subtitle} />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t.members.name}</TableHead>
            <TableHead className="hidden sm:table-cell">{t.members.email}</TableHead>
            <TableHead>{t.members.role}</TableHead>
            {manage ? <TableHead>{t.common.actions}</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.map((member) => (
            <TableRow key={member.id}>
              <TableCell className="whitespace-normal">
                {member.full_name}
                {member.user_id === me.id ? <span className="text-muted-foreground"> ({t.members.you})</span> : null}
              </TableCell>
              <TableCell className="hidden sm:table-cell">{member.email}</TableCell>
              <TableCell>
                {manage ? (
                  <ActionForm
                    action={changeMemberRoleAction.bind(null, companyId, member.id)}
                    submitLabel={t.members.changeRole}
                    pendingLabel={t.common.pending}
                    variant="outline"
                    className="flex-row items-end gap-2"
                  >
                    <SelectField
                      label={t.members.role}
                      name="role"
                      id={`role-${member.id}`}
                      defaultValue={member.role}
                      options={roleOptions}
                    />
                  </ActionForm>
                ) : (
                  t.roles[member.role]
                )}
              </TableCell>
              {manage ? (
                <TableCell>
                  <InlineAction
                    action={removeMemberAction.bind(null, companyId, member.id)}
                    label={t.common.remove}
                    pendingLabel={t.common.pending}
                    variant="destructive"
                    confirm={interpolate(t.members.removeConfirm, { name: member.full_name })}
                  />
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {manage ? (
        <Card className="mt-8 max-w-xl">
          <CardHeader>
            <CardTitle className="text-base">{t.members.addTitle}</CardTitle>
            <p className="text-muted-foreground text-sm">{t.members.addHint}</p>
          </CardHeader>
          <CardContent>
            <ActionForm
              action={addMemberAction.bind(null, companyId)}
              submitLabel={t.common.add}
              pendingLabel={t.common.pending}
              resetOnSuccess
            >
              <Field label={t.members.email} name="email" type="email" required />
              <SelectField label={t.members.role} name="role" defaultValue="PME_COMPTABLE" options={roleOptions} />
            </ActionForm>
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}
