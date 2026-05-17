// New React page rendered for every user — frontend reviewer should flag:
//   1. <img> with no `alt` attribute (a11y, WCAG 1.1.1)
//   2. dangerouslySetInnerHTML on user-controlled content (XSS)
//   3. No Content-Security-Policy header set anywhere
export default function ProfilePage({ user }: { user: { avatar: string; bioHtml: string } }) {
  return (
    <div>
      <img src={user.avatar} />
      <div dangerouslySetInnerHTML={{ __html: user.bioHtml }} />
    </div>
  );
}
