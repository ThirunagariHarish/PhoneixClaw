{{- define "phoenix.name" -}}
phoenix
{{- end }}

{{- define "phoenix.fullname" -}}
{{ .Release.Name }}
{{- end }}

{{- define "phoenix.labels" -}}
app.kubernetes.io/name: {{ include "phoenix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: phoenix
{{- end }}

{{- define "phoenix.selectorLabels" -}}
app.kubernetes.io/name: {{ include "phoenix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "phoenix.image" -}}
{{- $component := . -}}
{{- $root := $.root | default $ -}}
{{ $root.Values.image.repository }}/{{ $component }}:{{ $root.Values.image.tag }}
{{- end }}
