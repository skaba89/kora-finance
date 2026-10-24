import type { Metadata } from "next";

import { ActionForm } from "@/components/forms/action-form";
import { Field, SelectField } from "@/components/forms/field";
import { InlineAction } from "@/components/forms/inline-action";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  addMemberAction,
  changeMemberRoleAction,
  removeMemberAction,
  resendInvitationAction,
  revokeInvitationAction,
} from "@/lib/actions/companies";
import { can, getCompany, getCurrentUser, getInvitations, getMembers } from "@/lib/dal";
import { formatDate } from "@/lib/format";
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
  const [{ t, locale }, company, members, invitations, me] = await Promise.all([
    getDictionary(),
    getCompany(companyId),
    getMembers(companyId),
    getInvitations(companyId),
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

      <section className="mt-8" aria-labelledby="invitations-titre">
        <h2 id="invitations-titre" className="mb-2 text-base font-semibold">
          {t.members.invitationsTitle}
        </h2>
        {invitations.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t.members.invitationsEmpty}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t.members.email}</TableHead>
                <TableHead>{t.members.role}</TableHead>
                <TableHead className="hidden sm:table-cell">{t.members.expiresOn}</TableHead>
                {manage ? <TableHead>{t.common.actions}</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {invitations.map((invitation) => (
                <TableRow key={invitation.id}>
                  <TableCell className="whitespace-normal break-all">
                    {invitation.email}
                    {invitation.expired ? (
                      <Badge variant="destructive" className="ml-2">
                        {t.members.expired}
                      </Badge>
                    ) : invitation.sent_at === null ? (
                      <Badge variant="secondary" className="ml-2">
                        {t.members.notSent}
                      </Badge>
                    ) : null}
                  </TableCell>
                  <TableCell>{t.roles[invitation.role]}</TableCell>
                  <TableCell className="hidden sm:table-cell">
                    {formatDate(invitation.expires_at.slice(0, 10), locale)}
                  </TableCell>
                  {manage ? (
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <InlineAction
                          action={resendInvitationAction.bind(null, companyId, invitation.id)}
                          label={t.members.resend}
                          pendingLabel={t.common.pending}
                          showSuccess
                        />
                        <InlineAction
                          action={revokeInvitationAction.bind(null, companyId, invitation.id)}
                          label={t.members.revoke}
                          pendingLabel={t.common.pending}
                          variant="destructive"
                          confirm={interpolate(t.members.revokeConfirm, { email: invitation.email })}
                        />
                      </div>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>

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
