// fixture for iac_pulumi
import * as aws from "@pulumi/aws";
import * as pulumi from "@pulumi/pulumi";

const config = new pulumi.Config();

const bucket = new aws.s3.Bucket("my-bucket", {
    acl: "private",
    tags: { Environment: config.require("env") },
});

const table = new aws.dynamodb.Table("sessions", {
    attributes: [{ name: "session_id", type: "S" }],
    hashKey: "session_id",
    billingMode: "PAY_PER_REQUEST",
});

export const bucketName = bucket.id;
export const tableName = table.name;
