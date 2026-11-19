"""Local trusted provisioning; dry-run by default, explicit confirmation for writes."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ai_engine'))
from src.firebase import connect, validate_id


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', required=True)
    p.add_argument('--name', help='Profile display name, required for new profiles')
    p.add_argument('--caregiver-email', required=True, help='Firebase Auth caregiver email')
    p.add_argument('--create-user',action='store_true',help='Create a missing email account without a password; user sets password through reset flow')
    p.add_argument('--role',choices=['caregiver','viewer'],default='caregiver')
    p.add_argument('--revoke',action='store_true',help='Remove this user link without deleting the profile or Auth account')
    p.add_argument('--apply',action='store_true')
    p.add_argument('--confirm',help='Must exactly match the profile ID when applying')
    args = p.parse_args()
    validate_id(args.profile)
    if args.apply and args.confirm != args.profile:
        p.error('--confirm must exactly match --profile')
    db, app = connect()
    from firebase_admin import auth, firestore
    profile = db.collection('profiles').document(args.profile)
    snapshot=profile.get()
    exists = snapshot.exists
    if exists and args.name and snapshot.to_dict().get('displayName')!=args.name:
        p.error('Existing profile name differs; choose a different profile ID instead of linking the wrong person')
    if args.revoke and not exists:
        p.error('Cannot revoke from a profile that does not exist')
    if not args.revoke and not exists and not args.name:
        p.error('A new profile requires --name')
    try:
        user=auth.get_user_by_email(args.caregiver_email,app=app)
    except auth.UserNotFoundError:
        user=None
        if not args.create_user or args.revoke:
            p.error('Auth user does not exist. Use --create-user for a new caregiver account, then have the user set their password in the app.')
    operation='revoke membership' if args.revoke else 'link existing' if exists else 'create'
    print(f"{'APPLY' if args.apply else 'DRY RUN'}: {operation} profile {args.profile}, role {args.role}")
    if not args.apply:
        if user is None:print('Plan: create missing Auth account without password. No email or reset link is sent by this script.')
        return
    created_user=False
    if user is None:
        user=auth.create_user(email=args.caregiver_email,app=app)
        created_user=True
        # Validate password-setup support without storing, printing or sending the link.
        auth.generate_password_reset_link(args.caregiver_email,app=app)
        print('Auth account created. The caregiver should use Forgot password in the app to set a private password.')
    batch = db.batch()
    if args.revoke:
        batch.delete(profile.collection('caregivers').document(user.uid))
        batch.delete(db.collection('users').document(user.uid).collection('profiles').document(args.profile))
        batch.commit()
        print('Membership revoked. Profile and Auth account retained.')
        return
    if not exists:
        batch.create(profile,{'displayName':args.name,'createdAt':firestore.SERVER_TIMESTAMP,'schemaVersion':1})
    batch.set(profile.collection('caregivers').document(user.uid),{'role':args.role,'linkedAt':firestore.SERVER_TIMESTAMP})
    user_ref=db.collection('users').document(user.uid)
    if not user_ref.get().exists:
        batch.create(user_ref,{'createdAt':firestore.SERVER_TIMESTAMP})
    batch.set(db.collection('users').document(user.uid).collection('profiles').document(args.profile),{'profileId':args.profile,'role':args.role})
    batch.commit()
    membership=profile.collection('caregivers').document(user.uid).get().to_dict()
    link=user_ref.collection('profiles').document(args.profile).get().to_dict()
    if membership.get('role')!=args.role or link.get('profileId')!=args.profile:
        raise RuntimeError('Provisioning read-back verification failed')
    (Path(__file__).resolve().parents[1]/'docs/provisioning-status.json').write_text(json.dumps({
        'profile_id':args.profile,'role':args.role,'status':'PASS','read_back_verified':True,
        'auth_account_created':created_user,'password_setup_required':created_user},indent=2))
    print('Provisioning complete. No password, private key or FCM token logged.')


if __name__ == '__main__':
    main()
