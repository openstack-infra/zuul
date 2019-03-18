# Copyright (c) 2019 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

FROM opendevorg/python-builder as builder

# Optional location of Zuul API endpoint.
ARG REACT_APP_ZUUL_API
# Optional flag to enable React Service Worker. (set to true to enable)
ARG REACT_APP_ENABLE_SERVICE_WORKER

COPY . /tmp/src
RUN /tmp/src/tools/install-js-tools.sh
RUN assemble

# The wheel install method doesn't run the setup hooks as the source based
# installations do so we have to call zuul-manage-ansible here.
RUN /output/install-from-bindep && zuul-manage-ansible


FROM opendevorg/python-base as zuul

COPY --from=builder /output/ /output
RUN echo "deb http://ftp.debian.org/debian stretch-backports main" >> /etc/apt/sources.list \
  && apt-get update \
  && apt-get install -t stretch-backports -y bubblewrap \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*
RUN /output/install-from-bindep \
  && pip install --cache-dir=/output/wheels -r /output/zuul_base/requirements.txt \
  && rm -rf /output
VOLUME /var/lib/zuul
CMD ["/usr/local/bin/zuul"]

FROM zuul as zuul-executor
COPY --from=builder /output/ /output
COPY --from=builder /usr/local/lib/zuul/ /usr/local/lib/zuul
RUN pip install --cache-dir=/output/wheels -r /output/zuul_executor/requirements.txt \
  && rm -rf /output

CMD ["/usr/local/bin/zuul-executor"]

FROM zuul as zuul-fingergw
CMD ["/usr/local/bin/zuul-fingergw"]

FROM zuul as zuul-merger
CMD ["/usr/local/bin/zuul-merger"]

FROM zuul as zuul-scheduler
CMD ["/usr/local/bin/zuul-scheduler"]

FROM zuul as zuul-web
CMD ["/usr/local/bin/zuul-web"]
