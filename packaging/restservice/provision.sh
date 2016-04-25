#/bin/bash -e

#function build_rpm() {
#    echo "Building RPM..."
#    sudo yum install -y rpm-build redhat-rpm-config
#    sudo yum install -y python-devel gcc
#    sudo mkdir -p /root/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
#    sudo cp /vagrant/restservice/build.spec /root/rpmbuild/SPECS
#    sudo rpmbuild -ba /root/rpmbuild/SPECS/build.spec \
#        --define "VERSION $VERSION" \
#        --define "PRERELEASE $PRERELEASE" \
#        --define "BUILD $BUILD" \
#        --define "CORE_TAG_NAME $CORE_TAG_NAME" \
#        --define "PLUGINS_TAG_NAME $PLUGINS_TAG_NAME"
#    # This is the UGLIEST HACK EVER!
#    # Since rpmbuild spec files cannot receive a '-' in their version,
#    # we do this... thing and replace an underscore with a dash.
#    # cd /tmp/x86_64 &&
#    # sudo mv *.rpm $(ls *.rpm | sed 's|_|-|g')
#}

# VERSION/PRERELEASE/BUILD are exported to follow with our standard of exposing them as env vars. They are not used.
CORE_TAG_NAME="3.4m4"
curl https://raw.githubusercontent.com/cloudify-cosmo/cloudify-packager/${PACKAGER_BRANCH-$CORE_TAG_NAME}/common/provision.sh -o ./common-provision.sh &&
source common-provision.sh

AWS_ACCESS_KEY_ID=$1
AWS_ACCESS_KEY=$2
MANAGER_BRANCH=$3
PACKAGER_BRANCH=$4

rm -rf cloudify-manager
git clone https://github.com/cloudify-cosmo/cloudify-manager.git
cd cloudify-manager
git checkout ${MANAGER_BRANCH-$CORE_TAG_NAME}
cd packaging/restservice/omnibus
git tag -d $CORE_TAG_NAME
NEW_TAG_NAME="${VERSION}.${PRERELEASE}"
git tag $NEW_TAG_NAME
omnibus build cloudify && result="success"
cd pkg
cat *.json || exit 1
rm -f version-manifest.json

[ "$result" == "success" ] && create_md5 "rpm" &&
[ -z ${AWS_ACCESS_KEY} ] || upload_to_s3 "rpm" && upload_to_s3 "md5"
