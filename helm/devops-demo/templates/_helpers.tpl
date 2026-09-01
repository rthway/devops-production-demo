{{/* Chart name, overridable. */}}
{{- define "devops-demo.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified name. Truncated to 63 characters because that is the DNS label
limit -- a longer name produces resources Kubernetes silently refuses to
create a Service endpoint for.
*/}}
{{- define "devops-demo.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "devops-demo.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Labels on every object. */}}
{{- define "devops-demo.labels" -}}
helm.sh/chart: {{ include "devops-demo.chart" . }}
{{ include "devops-demo.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels only. Kept separate from the full label set because a
Deployment's selector is IMMUTABLE: if a mutable value such as the chart
version leaked in here, every chart bump would fail the upgrade with
"field is immutable" and require deleting the Deployment.
*/}}
{{- define "devops-demo.selectorLabels" -}}
app.kubernetes.io/name: {{ include "devops-demo.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "devops-demo.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "devops-demo.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* Image reference. Falls back to appVersion so the tag is never "latest". */}}
{{- define "devops-demo.image" -}}
{{- printf "%s:%s" .Values.image.repository (.Values.image.tag | default .Chart.AppVersion) }}
{{- end }}
