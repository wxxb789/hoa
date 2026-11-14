import type { PluginSurfaceProps } from "@getpaseo/plugin/client";
import { useRpc, useSettings, useTranslation } from "@getpaseo/plugin/client";
import {
  SettingsAction,
  SettingsCard,
  SettingsInput,
  SettingsRow,
  SettingsSection,
  SettingsSelect,
  useToast,
} from "@getpaseo/plugin/client/ui";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Text } from "react-native";
import { listRuns } from "../shared/runs";
import { observerSettings, type ObserverSettings } from "../shared/settings";
import { messages } from "./messages";
import { useObserverStyles } from "./styles";
import { sourceKey } from "./runs-browser";

const POLL_OPTIONS = [1000, 2000, 5000, 15000, 30000];
const TAIL_OPTIONS = [40, 80, 200, 500];
const DEFAULT_PLACEHOLDER = "C:\\Users\\you\\.local\\state\\gdd\\runs";

/**
 * Settings screen: the run root override plus poll cadence and tail length. The resolved root is
 * read back from the same scan the panel uses, so a wrong path is visible immediately.
 */
export function ObserverSettingsScreen({ theme, layout }: PluginSurfaceProps) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  const toast = useToast();
  const settings = useSettings(observerSettings);
  const list = useRpc(listRuns);
  const [draft, setDraft] = useState<string | null>(null);

  const scan = useQuery({
    queryKey: ["gddRuns", "list"],
    queryFn: () => list({}),
    refetchInterval: 10_000,
  });

  const values = settings.status === "ready" ? settings.values : null;
  const revision =
    settings.status === "ready" || settings.status === "invalid" ? settings.revision : null;
  const rootDraft = draft ?? values?.runRoot ?? "";
  const pollOptions = useMemo(
    () =>
      POLL_OPTIONS.map((ms) => ({
        label: t("settingsScreen.pollOption", { seconds: ms / 1000 }),
        value: String(ms),
      })),
    [t],
  );
  const tailOptions = useMemo(
    () =>
      TAIL_OPTIONS.map((lines) => ({
        label: t("settingsScreen.tailOption", { count: lines }),
        value: String(lines),
      })),
    [t],
  );

  async function save(patch: Partial<ObserverSettings>) {
    if (!values || revision === null) return;
    const saved = await settings.save({ ...values, ...patch }, revision);
    if (saved) toast.show(t("settingsScreen.saved"), { variant: "success" });
    else toast.error(settings.saveError ?? t("settingsScreen.saveFailed"));
  }

  async function saveRoot() {
    const next = rootDraft.trim();
    if (next !== "" && !isAbsolutePath(next)) {
      toast.error(t("settingsScreen.rootError"));
      return;
    }
    if (next === (values?.runRoot ?? "")) return;
    await save({ runRoot: next });
    setDraft(null);
  }

  if (settings.status !== "ready") {
    if (settings.status === "loading") {
      return <Text style={styles.muted}>{t("settingsScreen.loading")}</Text>;
    }
    return (
      <Text style={styles.error}>{t("settingsScreen.invalid", { error: settings.error })}</Text>
    );
  }

  const rootExists = scan.data?.rootExists === true;
  return (
    <>
      <SettingsSection title={t("settingsScreen.root")} info={t("settingsScreen.rootHint")}>
        <SettingsCard>
          <SettingsInput
            label={t("settingsScreen.root")}
            hint={t("settingsScreen.rootHint")}
            error={!rootExists && rootDraft.trim() !== "" ? t("list.missing") : null}
            placeholder={DEFAULT_PLACEHOLDER}
            initialValue={settings.values.runRoot}
            onChangeText={setDraft}
          />
          <SettingsAction
            label={t("settingsScreen.save")}
            actionLabel={t("settingsScreen.save")}
            onPress={() => void saveRoot()}
          />
          <SettingsAction
            label={t("settingsScreen.clear")}
            actionLabel={t("settingsScreen.clear")}
            onPress={() => {
              setDraft("");
              void save({ runRoot: "" });
            }}
          />
        </SettingsCard>
      </SettingsSection>
      <SettingsSection title={t("settingsScreen.resolved")}>
        <SettingsCard>
          <SettingsRow label={t("settingsScreen.resolved")}>
            <Text style={styles.body} selectable>
              {scan.data?.runRoot ?? t("list.scanning")}
            </Text>
          </SettingsRow>
          <SettingsRow label={t("settingsScreen.resolvedFrom")}>
            <Text style={styles.body}>{t(sourceKey(scan.data?.rootSource ?? "default"))}</Text>
          </SettingsRow>
          <SettingsRow label={t("settingsScreen.exists")}>
            <Text style={styles.body}>
              {rootExists ? t("settingsScreen.yes") : t("settingsScreen.no")}
            </Text>
          </SettingsRow>
          <SettingsRow label={t("settingsScreen.probe")}>
            <Text style={styles.body}>{scan.data?.probe ?? "—"}</Text>
          </SettingsRow>
          <SettingsRow label={t("list.runs")}>
            <Text style={styles.body}>{t("list.count", { count: scan.data?.runs.length ?? 0 })}</Text>
          </SettingsRow>
          <SettingsRow label={t("settingsScreen.candidates")}>
            <Text style={styles.muted} selectable>
              {(scan.data?.candidates ?? [])
                .map(
                  (candidate) =>
                    `${candidate.exists ? "✓" : "·"} ${candidate.path} (${t(sourceKey(candidate.source))})`,
                )
                .join("\n")}
            </Text>
          </SettingsRow>
          {scan.error ? (
            <Text style={styles.error}>{t("error.list", { error: message(scan.error) })}</Text>
          ) : null}
        </SettingsCard>
      </SettingsSection>
      <SettingsSection title={t("settingsScreen.poll")}>
        <SettingsCard>
          <SettingsSelect
            label={t("settingsScreen.poll")}
            value={String(settings.values.pollIntervalMs)}
            options={pollOptions}
            onValueChange={(value) => void save({ pollIntervalMs: Number(value) })}
          />
          <SettingsSelect
            label={t("settingsScreen.tail")}
            value={String(settings.values.tailLines)}
            options={tailOptions}
            onValueChange={(value) => void save({ tailLines: Number(value) })}
          />
        </SettingsCard>
      </SettingsSection>
    </>
  );
}

function isAbsolutePath(path: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(path) || path.startsWith("/") || path.startsWith("\\\\");
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
