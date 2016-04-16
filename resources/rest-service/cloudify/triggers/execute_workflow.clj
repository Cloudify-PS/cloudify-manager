(fn execute-workflow
  [ctx]
    (let [deployment-id         (:deployment_id ctx)
          parameters            (:trigger-parameters ctx)
          manager-rest-host     (or (System/getenv "REST_HOST") "127.0.0.1")
          manager-rest-protocol (or (System/getenv "REST_PROTOCOL") "http")
          raw-manager-rest-port (or (System/getenv "REST_PORT") "80")
          manager-rest-port     (Integer/parseInt raw-manager-rest-port)
          raw-verify-ssl-cert   (or (System/getenv "VERIFY_SSL_CERTIFICATE") "false")
          verify-ssl-cert       (Boolean/valueOf raw-verify-ssl-cert)
          base-uri              (str manager-rest-protocol "://" manager-rest-host ":" manager-rest-port "/api/v2")
          endpoint              (str "/executions")
          resource-uri          (str base-uri endpoint)
          body                  (cheshire.core/generate-string {
                                  :deployment_id           deployment-id
                                  :workflow_id             (:workflow parameters)
                                  :force                   (:force parameters)
                                  :allow_custom_parameters (:allow_custom_parameters parameters)
                                  :parameters              (:workflow_parameters parameters)})]
      (clj-http.client/post resource-uri
        {:content-type   :json
         :accept         :json
         :socket-timeout (:socket_timeout parameters)
         :conn-timeout   (:conn_timeout parameters)
         :insecure?      (not= verify-ssl-cert true)
         :body           body})))
