from app.schemas.content import AboutOut, AboutSocialOut, FaqItemOut


class ContentService:
    def about(self) -> AboutOut:
        return AboutOut(
            brand_name="TecTach",
            tagline="AI Fitness & Training Solution",
            address_lines=["578 Boolean Ave", "Turing St", "New York, NY"],
            phones=["+123-456-789", "+44-887-449"],
            social=AboutSocialOut(
                facebook="https://facebook.com/tectach",
                instagram="https://instagram.com/tectach",
                linkedin="https://linkedin.com/company/tectach",
                youtube="https://youtube.com/@tectach",
            ),
        )

    def faq(self) -> list[FaqItemOut]:
        return [
            FaqItemOut(
                id="what",
                question="What is TecTach?",
                answer=(
                    "TecTach is an AI fitness and training app for coaches and athletes. "
                    "Trainers program workouts, review nutrition, and coach form. "
                    "Trainees log sessions, meals, and follow assigned plans."
                ),
            ),
            FaqItemOut(
                id="roles",
                question="Can I use one app as a trainer and a trainee?",
                answer="Yes. One app supports both roles. Sign in with the account type you created.",
            ),
            FaqItemOut(
                id="link",
                question="How do I connect with my trainer?",
                answer="Ask your trainer for their invite code, then enter it on the link trainer screen.",
            ),
            FaqItemOut(
                id="assessment",
                question="What does the fitness assessment do?",
                answer=(
                    "It builds a weekly training plan from your goals, schedule, and preferences. "
                    "It does not diagnose medical conditions."
                ),
            ),
        ]
